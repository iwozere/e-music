import uuid
import asyncio
from typing import Optional
from sqlmodel import Session, select, or_

from app.models import Track
from app.services import ytmusic
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)


def _looks_like_youtube_video_id(tid: str) -> bool:
    """Match routers/tracks.py heuristic: raw video id, not an internal UUID."""
    if not tid or len(tid) > 32:
        return False
    if len(tid) == 36 and tid.count("-") == 4:
        return False
    return all(c.isalnum() or c in "_-" for c in tid)


def _album_from_get_song(yt_info: dict) -> Optional[str]:
    alb = yt_info.get("album")
    if isinstance(alb, dict):
        name = alb.get("name")
        return str(name).strip() if name else None
    if isinstance(alb, str) and alb.strip():
        return alb.strip()
    return None


async def ensure_track_exists(session: Session, track_id: str) -> Optional[Track]:
    """
    Ensure a track exists in the database. 
    If not found, attempts to index it from YouTube metadata if it looks like a YT ID.
    Returns the Track object if found/created, else None.
    """
    track = session.exec(select(Track).where(or_(Track.id == track_id, Track.remote_id == track_id))).first()
    if track:
        return track

    if _looks_like_youtube_video_id(track_id):
        _logger.info("Track %s not found in DB. Attempting auto-indexing.", track_id)
        try:
            yt_info = await asyncio.to_thread(ytmusic.yt.get_song, track_id)
            if yt_info and "videoDetails" in yt_info:
                details = yt_info["videoDetails"]
                thumbnails = details.get("thumbnail", {}).get("thumbnails", [])
                thumb_url = thumbnails[-1].get("url") if thumbnails else None
                duration = None
                ls = details.get("lengthSeconds")
                if ls is not None:
                    try:
                        duration = int(ls)
                    except (TypeError, ValueError):
                        pass
                album_name = _album_from_get_song(yt_info)

                new_track = Track(
                    id=str(uuid.uuid4()),
                    title=details.get("title", "Unknown Title"),
                    artist=details.get("author", "Unknown Artist"),
                    album=album_name,
                    remote_id=track_id,
                    source_type="youtube",
                    thumbnail=thumb_url,
                    duration=duration,
                )
                session.add(new_track)
                session.commit()
                session.refresh(new_track)
                return new_track
        except Exception:
            _logger.exception("Failed to auto-index track: %s", track_id)
    
    return None
