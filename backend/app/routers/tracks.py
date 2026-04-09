import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlmodel import Session, col, func, or_, select

from app.auth_utils import sign_stream_url, verify_stream_params
from app.config import settings
from app.db import get_session
from app.public_api import api_v1_base_url
from app.dependencies import get_current_user, get_optional_user
from app.limiter_ext import limiter
from app.models import Track, User, UserActivity
from app.schemas import StreamGrantBody
from app.services import streamer
from app.services.library_import import is_under_music_path, schedule_import_cached_file
from app.services.track_service import ensure_track_exists
from app.services.ytmusic import get_related_tracks, get_track_thumbnail, search_youtube
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

router = APIRouter(prefix="/tracks", tags=["tracks"])


def _valid_stream_track_id(tid: str) -> bool:
    if not tid or len(tid) > 128:
        return False
    return all(c.isalnum() or c in "-_" for c in tid)


# Internal Cache for Search
SEARCH_CACHE: dict[str, dict[str, Any]] = {}
CACHE_TTL = 300  # 5 minutes

@router.get("/search", response_model=List[dict])
@limiter.limit("90/minute")
async def search(
    request: Request,
    q: str, 
    offset: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session), 
    current_user: Optional[User] = Depends(get_optional_user)
) -> List[dict]:
    """
    Search for tracks across local library and YouTube Music.
    Uses in-memory caching to optimize paginated requests.
    """
    if not q or not q.strip():
        _logger.info("Empty search query received, returning empty list")
        return []

    start_time = time.time()
    _logger.info("Searching for: %s (offset: %s, limit: %s)", q, offset, limit)
    
    # 1. Search local DB (Python-side filtering for robust Cyrillic support)
    q_lower = q.lower()
    
    # We fetch all tracks; with 3000-5000 tracks this is extremely fast and more reliable than SQLite LOWER
    all_local_db = session.exec(select(Track)).all()
    
    all_local = []
    for t in all_local_db:
        # Check title, artist, or album
        search_target = f"{t.title or ''} {t.artist or ''} {t.album or ''}".lower()
        if q_lower in search_target:
            all_local.append(t)
    
    local_count = len(all_local)
    _logger.info("Local search complete in %.3fs: %s matches.", time.time() - start_time, local_count)
    
    local_results = []
    if offset < local_count:
        local_results = all_local[offset : offset + limit]
    
    # 2. YouTube Search (Virtual Pagination)
    needed_from_yt = limit - len(local_results)
    yt_offset = max(0, offset - local_count)

    yt_data: list = []
    if needed_from_yt > 0:
        now = datetime.now().timestamp()
        if q in SEARCH_CACHE and SEARCH_CACHE[q]["expires"] > now:
            yt_data = SEARCH_CACHE[q]["results"]
        else:
            try:
                yt_data = await asyncio.to_thread(search_youtube, q, limit=100)
                SEARCH_CACHE[q] = {"results": yt_data, "expires": now + CACHE_TTL}
            except Exception:
                _logger.exception("YouTube Search Error")
                yt_data = []

    # 3. Assemble final results — local tracks first, then YouTube with dedup compensation.
    # Instead of a fixed slice, walk the YT cache with a sliding window so that
    # items skipped by deduplication are replaced by the next available result.
    local_ids_in_results = {t.id for t in local_results}

    final_results = []
    for t in local_results:
        d = t.model_dump()
        d["is_cached"] = t.is_cached
        final_results.append(d)

    if needed_from_yt > 0 and yt_data:
        WINDOW = needed_from_yt * 3  # over-fetch factor to cover expected duplicates
        scan_pos = yt_offset

        while len(final_results) < limit and scan_pos < len(yt_data):
            window = yt_data[scan_pos : scan_pos + WINDOW]
            scan_pos += len(window)

            # Batch-resolve which window items already exist in the local DB
            window_remote_ids = [item["remote_id"] for item in window if item.get("remote_id")]
            db_matches: dict = {}
            if window_remote_ids:
                stmt = select(Track).where(col(Track.remote_id).in_(window_remote_ids))
                db_matches = {m.remote_id: m for m in session.exec(stmt).all()}

            for yt_item in window:
                if len(final_results) >= limit:
                    break
                remote_id = yt_item.get("remote_id")
                if remote_id in db_matches:
                    db_track = db_matches[remote_id]
                    if db_track.id not in local_ids_in_results:
                        # Already indexed locally — use the richer DB record
                        d = db_track.model_dump()
                        d["is_cached"] = db_track.is_cached
                        final_results.append(d)
                        local_ids_in_results.add(db_track.id)  # prevent re-adding same track
                    # else: duplicate of something already on this page — skip silently
                else:
                    final_results.append(yt_item)

    # 4. Enrich with liked status
    if current_user:
        likes_stmt = select(UserActivity.track_id).where(
            UserActivity.user_id == current_user.id,
            UserActivity.is_liked,
        )
        likes = set(session.exec(likes_stmt).all())
        for item in final_results:
            item["is_liked"] = item.get("id") in likes

    _logger.info("Search returned %s total results in %.3fs for: %s", len(final_results), time.time() - start_time, q)
    return final_results

@router.get("/popular")
async def get_popular_tracks(
    offset: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user)
) -> List[dict]:
    """
    Fetch popular tracks from the local library based on global play counts.
    """
    # Query tracks and sum their play counts across all users
    statement = (
        select(Track, func.sum(UserActivity.play_count).label("total_plays"))
        .outerjoin(UserActivity, col(UserActivity.track_id) == col(Track.id))
        .group_by(Track.id)
        .order_by(func.sum(UserActivity.play_count).desc(), col(Track.added_at).desc())
        .offset(offset)
        .limit(limit)
    )
    results = session.exec(statement).all()
    
    final_results = []
    
    # Get user likes if logged in
    likes = set()
    if current_user:
        likes_stmt = select(UserActivity.track_id).where(
            UserActivity.user_id == current_user.id,
            UserActivity.is_liked,
        )
        likes = set(session.exec(likes_stmt).all())

    for track, total_plays in results:
        t_dict = track.model_dump()
        t_dict["is_liked"] = t_dict["id"] in likes
        t_dict["total_plays"] = int(total_plays or 0)
        final_results.append(t_dict)
        
    return final_results

@router.post("/{track_id}/like")
async def like_track(
    track_id: str, 
    is_liked: bool = True, 
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Toggle 'liked' status for a specific track.
    """
    _logger.info("User %s liking track %s: %s", current_user.id, track_id, is_liked)
    track = await ensure_track_exists(session, track_id)
    
    if not track:
        raise HTTPException(status_code=404, detail="Track not found and could not be indexed.")

    # Update user activity
    activity_statement = select(UserActivity).where(
        UserActivity.user_id == current_user.id, 
        UserActivity.track_id == track.id
    )
    activity = session.exec(activity_statement).first()
    
    if not activity:
        activity = UserActivity(user_id=current_user.id, track_id=track.id, is_liked=is_liked)
        session.add(activity)
    else:
        activity.is_liked = is_liked
        session.add(activity)
    
    session.commit()
    return {"status": "success", "is_liked": is_liked}

@router.get("/recent")
async def get_recent_tracks(
    offset: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user)
) -> List[dict]:
    """
    Fetch recently added or modified tracks.
    """
    statement = (
        select(Track)
        .order_by(col(Track.added_at).desc())
        .offset(offset)
        .limit(limit)
    )
    results = session.exec(statement).all()
    
    final_results = []
    likes = set()
    if current_user:
        likes_stmt = select(UserActivity.track_id).where(
            UserActivity.user_id == current_user.id,
            UserActivity.is_liked,
        )
        likes = set(session.exec(likes_stmt).all())

    for track in results:
        t_dict = track.model_dump()
        t_dict["is_liked"] = t_dict["id"] in likes
        final_results.append(t_dict)
        
    return final_results

@router.post("/{track_id}/play")
async def track_played(
    track_id: str, 
    session: Session = Depends(get_session), 
    current_user: Optional[User] = Depends(get_optional_user)
) -> dict:
    """
    Record a play event for a track and increment play count.
    """
    if not current_user:
        _logger.debug("Guest play event for track %s (not recorded)", track_id)
        return {"status": "ignored"}

    _logger.info("User %s played track %s", current_user.id, track_id)
    track = await ensure_track_exists(session, track_id)
    
    if not track:
        return {"status": "ignored"}

    activity_statement = select(UserActivity).where(
        UserActivity.user_id == current_user.id, 
        UserActivity.track_id == track.id
    )
    activity = session.exec(activity_statement).first()
    
    if not activity:
        activity = UserActivity(
            user_id=current_user.id, 
            track_id=track.id, 
            play_count=1, 
            last_played=datetime.now(timezone.utc)
        )
        session.add(activity)
    else:
        activity.play_count += 1
        activity.last_played = datetime.now(timezone.utc)
        session.add(activity)
        
        # Trigger persistent caching on the 3rd play (YouTube sources only)
        if activity.play_count == 3 and track.remote_id:
            _logger.info("Track %s reached threshold (3 plays). Promoting to persistent cache.", track.id)
            from app.services.cache_manager import promote_track_to_cache

            promote_track_to_cache(track.remote_id)
    
    session.commit()
    return {"status": "success", "play_count": activity.play_count}

@router.get("/liked")
async def get_liked_tracks(
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> List[dict]:
    """
    Fetch all tracks that the current user has 'liked', with thumbnail backfill.
    """
    statement = select(Track).join(UserActivity).where(
        UserActivity.user_id == current_user.id,
        UserActivity.is_liked,
    )
    liked_tracks = session.exec(statement).all()
    
    results = []
    updated = False
    for t in liked_tracks:
        track_dict = t.model_dump()
        # Proactive Backfill: If YT track missing thumbnail, fetch it now
        if t.source_type == "youtube" and not t.thumbnail and t.remote_id:
            thumb = await get_track_thumbnail(t.remote_id)
            if thumb:
                t.thumbnail = thumb
                track_dict["thumbnail"] = thumb
                session.add(t)
                updated = True
        
        results.append(track_dict)
    
    if updated:
        session.commit()
        
    return results


@router.post("/stream/grant")
@limiter.limit("120/minute")
async def grant_stream_url(
    request: Request,
    body: StreamGrantBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Issue a short-lived signed URL for /tracks/stream/{track_id} (no JWT in query).
    """
    tid = body.track_id.strip()
    if not _valid_stream_track_id(tid):
        raise HTTPException(status_code=400, detail="Invalid track_id")
    statement = select(Track).where(or_(Track.id == tid, Track.remote_id == tid))
    if not session.exec(statement).first():
        raise HTTPException(status_code=404, detail="Track not found")
    exp = int(time.time()) + settings.STREAM_URL_TTL_SECONDS
    sig = sign_stream_url(tid, exp, current_user.id)
    base = api_v1_base_url(request)
    from urllib.parse import quote

    stream_url = f"{base}/tracks/stream/{tid}?exp={exp}&sig={sig}&uid={quote(current_user.id, safe='')}"
    return {
        "stream_url": stream_url,
        "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(),
    }


@router.get("/stream/{track_id}")
@limiter.limit("200/minute")
async def stream_track(
    request: Request,
    track_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    exp: Optional[int] = Query(None),
    sig: Optional[str] = Query(None),
    uid: Optional[str] = Query(None),
) -> Any:
    """
    Stream a track's audio data. Requires a short-lived signed URL from POST /tracks/stream/grant.
    """
    if exp is None or not sig or not uid:
        raise HTTPException(
            status_code=401,
            detail="Valid stream credentials required; obtain a signed URL via POST .../tracks/stream/grant",
        )
    if not _valid_stream_track_id(track_id):
        raise HTTPException(status_code=400, detail="Invalid track_id")
    if not verify_stream_params(track_id, exp, uid, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired stream link")
    if not session.get(User, uid):
        raise HTTPException(status_code=403, detail="Invalid stream subject")
    library_uid = uid
    _logger.info("Streaming request for: %s", track_id)
    statement = select(Track).where(or_(Track.id == track_id, Track.remote_id == track_id))
    track = session.exec(statement).first()

    # Check cache validity (min 100KB for audio)
    if track and track.is_cached and track.local_path:
        if os.path.exists(track.local_path):
            file_size = os.path.getsize(track.local_path)
            # Basic sanity check: an audio file should be > 100KB unless it's a very short sound
            if file_size > 100 * 1024:
                _logger.info("Streaming from local cache: %s (%s bytes)", track.local_path, file_size)
                if (
                    library_uid
                    and track.source_type == "youtube"
                    and track.remote_id
                    and not is_under_music_path(track.local_path)
                ):
                    background_tasks.add_task(
                        schedule_import_cached_file,
                        library_uid,
                        track.remote_id,
                        track.local_path,
                    )
                return streamer.get_local_stream(track.local_path)
            else:
                _logger.warning("Cache file %s is suspiciously small (%d bytes). Invaliding.", track.local_path, file_size)
                # Mark as not cached so we re-download it
                track.is_cached = False
                track.local_path = None
                session.add(track)
                session.commit()
                # Proceed to stream_youtube fallback
        else:
            _logger.warning("Track marked as cached but file missing at: %s. Falling back to YT.", track.local_path)
            track.is_cached = False
            track.local_path = None
            session.add(track)
            session.commit()
            # Proceed to stream_youtube fallback

    remote_key: str = (track.remote_id or track_id) if track else track_id
    _logger.info("Streaming from YouTube: %s", remote_key)
    # Only trust on-disk {remote_id}.mp3 when DB says cached; else avoid 416
    # from truncated orphans while still marked not cached in the UI.
    allow_disk = track.is_cached if track else True
    return await streamer.stream_youtube(
        remote_key,
        allow_disk_cache=allow_disk,
        library_user_id=library_uid,
    )


@router.get("/{track_id}")
# Intentionally no rate limit (metadata fetches are lightweight; search is limited).
async def get_track(
    track_id: str,
    session: Session = Depends(get_session)
) -> dict:
    """
    Fetch metadata for a single track by ID (internal or remote).
    """
    statement = select(Track).where(or_(Track.id == track_id, Track.remote_id == track_id))
    track = session.exec(statement).first()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    if track.source_type == "youtube" and not track.thumbnail and track.remote_id:
        thumb = await get_track_thumbnail(track.remote_id)
        if thumb:
            track.thumbnail = thumb
            session.add(track)
            session.commit()
            session.refresh(track)

    return track.model_dump()


@router.get("/{track_id}/related")
async def get_related(
    track_id: str,
    session: Session = Depends(get_session),
) -> List[dict]:
    """
    Radio Mode: Fetch related tracks based on a track ID.
    """
    _logger.info("Radio Mode requested for track: %s", track_id)
    statement = select(Track).where(or_(Track.id == track_id, Track.remote_id == track_id))
    track = session.exec(statement).first()
    remote_key: str = track.remote_id if track and track.remote_id else track_id

    related = await get_related_tracks(remote_key)
    return related
