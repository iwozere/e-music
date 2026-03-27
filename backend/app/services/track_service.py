import uuid
import asyncio
from typing import Optional
from sqlmodel import Session, select, or_

from app.models import Track
from app.services import ytmusic
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

async def ensure_track_exists(session: Session, track_id: str) -> Optional[Track]:
    """
    Ensure a track exists in the database. 
    If not found, attempts to index it from YouTube metadata if it looks like a YT ID.
    Returns the Track object if found/created, else None.
    """
    track = session.exec(select(Track).where(or_(Track.id == track_id, Track.remote_id == track_id))).first()
    if track:
        return track

    # Attempt auto-indexing for YouTube IDs (usually 11 chars)
    if len(track_id) == 11:
        _logger.info("Track %s not found in DB. Attempting auto-indexing.", track_id)
        try:
            yt_info = await asyncio.to_thread(ytmusic.yt.get_song, track_id)
            if yt_info and "videoDetails" in yt_info:
                details = yt_info["videoDetails"]
                thumbnails = details.get("thumbnail", {}).get("thumbnails", [])
                thumb_url = thumbnails[-1].get("url") if thumbnails else None
                
                new_track = Track(
                    id=str(uuid.uuid4()),
                    title=details.get("title", "Unknown Title"),
                    artist=details.get("author", "Unknown Artist"),
                    remote_id=track_id,
                    source_type="youtube",
                    thumbnail=thumb_url
                )
                session.add(new_track)
                session.commit()
                session.refresh(new_track)
                return new_track
        except Exception:
            _logger.exception("Failed to auto-index track: %s", track_id)
    
    return None
