import os
import shutil
from pathlib import Path
from typing import Optional

from app.config import settings
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

CACHE_DIR = Path(settings.CACHE_DIR)
TEMP_DIR = Path(settings.TEMP_DIR)
LIBRARY_DIR = Path(settings.MUSIC_PATH)
MAX_CACHE_SIZE_GB = 5

def get_dir_size(path: Path) -> int:
    """Calculate total size of a directory in bytes."""
    return sum(f.stat().st_size for f in path.glob('**/*') if f.is_file())

def enforce_cache_limit():
    """Delete oldest files in cache if limit is exceeded."""
    if not CACHE_DIR.exists():
        return

    current_size = get_dir_size(CACHE_DIR)
    limit_bytes = MAX_CACHE_SIZE_GB * 1024 * 1024 * 1024

    if current_size > limit_bytes:
        _logger.info("Cache limit exceeded (%d bytes). Cleaning up...", current_size)
        # Get files sorted by access time (oldest first)
        # We could also use some logic to NOT delete tracks with high play counts
        files = sorted(CACHE_DIR.glob('*'), key=os.path.getatime)
        
        for file in files:
            if current_size <= limit_bytes:
                break
            file_size = file.stat().st_size
            try:
                os.remove(file)
                current_size -= file_size
                _logger.info("Removed cached file: %s", file.name)
            except Exception:
                _logger.exception("Failed to remove cached file: %s", file.name)

# Supported cache artifact extensions (legacy .mp3 + new passthrough containers).
_CACHE_EXTS: tuple[str, ...] = (".mp3", ".webm", ".aac", ".m4a")


def _find_existing_artifact(directory: Path, track_id: str) -> Optional[Path]:
    for ext in _CACHE_EXTS:
        candidate = directory / f"{track_id}{ext}"
        if candidate.exists():
            return candidate
    return None


def promote_track_to_cache(track_id: str):
    """
    Move a track from temp cache to persistent cache once it hits the threshold.

    Works for any supported artifact extension so opus/webm and aac/adts files
    produced by the passthrough pipeline are promoted the same way as legacy MP3.
    """
    existing_persistent = _find_existing_artifact(CACHE_DIR, track_id)
    if existing_persistent is not None:
        os.utime(existing_persistent, None)  # Refresh timestamp (LRU)
        _logger.info("Track %s already in persistent cache. Updated timestamp.", track_id)
        return

    temp_path = _find_existing_artifact(TEMP_DIR, track_id)
    if temp_path is None:
        _logger.warning("Promotion failed: temp file for %s not found.", track_id)
        return

    persistent_path = CACHE_DIR / temp_path.name
    try:
        _logger.info("Moving track %s to persistent cache...", track_id)
        os.makedirs(CACHE_DIR, exist_ok=True)
        shutil.move(str(temp_path), str(persistent_path))

        from sqlmodel import Session, select
        from app.db import engine
        from app.models import Track
        with Session(engine) as db_session:
            stmt = select(Track).where(Track.remote_id == track_id)
            track = db_session.exec(stmt).first()
            if track:
                track.is_cached = True
                track.local_path = str(persistent_path)
                db_session.add(track)
                db_session.commit()

        enforce_cache_limit()
    except Exception:
        _logger.exception("Failed to promote track %s to persistent cache", track_id)

def is_track_cached(track_id: str) -> bool:
    """Check if a track is available in the persistent cache (any supported extension)."""
    return _find_existing_artifact(CACHE_DIR, track_id) is not None

def get_cache_path(track_id: str) -> str:
    """Return the absolute path to a cached track (first matching extension)."""
    match = _find_existing_artifact(CACHE_DIR, track_id)
    if match is not None:
        return str(match)
    # Default to legacy .mp3 if nothing exists yet; callers should check is_track_cached first.
    return str(CACHE_DIR / f"{track_id}.mp3")

async def cache_track(track_id: str, stream_url: str):
    """
    Download and store a track in the persistent cache.
    Note: Real implementation would use yt-dlp or similar. 
    For now, we assume the track is being indexed or streamed.
    """
    # This is a placeholder for the actual background download logic.
    # In this app architecture, tracks are usually downloaded during indexing.
    # We will repurpose the existing library logic to 'promote' popular tracks to cache.
    pass
