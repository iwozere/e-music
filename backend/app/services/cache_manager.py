import os
import shutil
from pathlib import Path
from typing import List
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

from app.config import settings

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

def promote_track_to_cache(track_id: str):
    """
    Move a track from temp cache to persistent cache once it hits the threshold.
    """
    temp_path = TEMP_DIR / f"{track_id}.mp3"
    persistent_path = CACHE_DIR / f"{track_id}.mp3"
    
    if persistent_path.exists():
        os.utime(persistent_path, None) # Refresh timestamp
        _logger.info("Track %s already in persistent cache. Updated timestamp.", track_id)
        return

    if temp_path.exists():
        try:
            _logger.info("Moving track %s to persistent cache...", track_id)
            os.makedirs(CACHE_DIR, exist_ok=True)
            shutil.move(str(temp_path), str(persistent_path))
            
            # Update DB status
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
    else:
        _logger.warning("Promotion failed: temp file for %s not found.", track_id)

def is_track_cached(track_id: str) -> bool:
    """Check if a track is available in the persistent cache."""
    cache_path = CACHE_DIR / f"{track_id}.mp3"
    return cache_path.exists()

def get_cache_path(track_id: str) -> str:
    """Return the absolute path to a cached track."""
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
