"""Track search, metadata, likes, play counts, and audio streaming routes."""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, List, NamedTuple, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import desc
from sqlmodel import Session, col, func, or_, select

from app.auth_utils import sign_stream_url, verify_stream_params
from app.config import settings
from app.db import get_session
from app.dependencies import get_current_user, get_optional_user
from app.limiter_ext import limiter
from app.models import Track, User, UserActivity
from app.public_api import api_v1_base_url
from app.schemas import StreamGrantBody
from app.services import streamer
from app.services.cache_manager import promote_track_to_cache
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


def _youtube_video_id_len_ok(rid: str) -> bool:
    """YouTube ids are typically 11 chars; allow a small range for future formats."""
    return 6 <= len(rid) <= 32


def _looks_like_youtube_video_id(tid: str) -> bool:
    """True if this is probably a raw video id (not an internal UUID)."""
    if not tid or len(tid) > 32:
        return False
    # Internal UUIDs are 36 chars with four hyphens; never pass those to yt-dlp as a video id.
    if len(tid) == 36 and tid.count("-") == 4:
        return False
    return all(c.isalnum() or c in "_-" for c in tid)


# Internal Cache for Search
SEARCH_CACHE: dict[str, dict[str, Any]] = {}
CACHE_TTL = 300  # 5 minutes


class _YoutubeMergeParams(NamedTuple):
    needed_from_yt: int
    yt_offset: int
    limit: int
    local_results: List[Track]


def _filter_local_tracks_for_query(tracks: List[Track], q_lower: str) -> List[Track]:
    """Python-side substring match on title, artist, album (robust for Cyrillic, etc.)."""
    out: List[Track] = []
    for t in tracks:
        search_target = f"{t.title or ''} {t.artist or ''} {t.album or ''}".lower()
        if q_lower in search_target:
            out.append(t)
    return out


async def _get_cached_or_fetch_youtube(q: str) -> list:
    """Return cached YouTube search results or fetch (with in-memory TTL cache)."""
    now = datetime.now().timestamp()
    if q in SEARCH_CACHE and SEARCH_CACHE[q]["expires"] > now:
        return SEARCH_CACHE[q]["results"]
    try:
        yt_data = await asyncio.to_thread(search_youtube, q, limit=100)
    except Exception:  # pylint: disable=broad-exception-caught
        # ytmusic / network stack may raise arbitrary exceptions
        _logger.exception("YouTube Search Error")
        return []
    SEARCH_CACHE[q] = {"results": yt_data, "expires": now + CACHE_TTL}
    return yt_data


def _tracks_by_remote_id(session: Session, remote_ids: List[str]) -> dict:
    """Map remote_id -> Track for a batch of YouTube ids."""
    if not remote_ids:
        return {}
    stmt = select(Track).where(col(Track.remote_id).in_(remote_ids))
    return {m.remote_id: m for m in session.exec(stmt).all()}


def _merge_youtube_with_dedup(  # pylint: disable=too-many-locals
    session: Session,
    yt_data: list,
    params: _YoutubeMergeParams,
) -> List[dict]:
    """Append YouTube rows to local results, substituting DB rows when already indexed."""
    needed_from_yt = params.needed_from_yt
    yt_offset = params.yt_offset
    limit = params.limit
    local_results = params.local_results

    local_ids_in_results: Set[str] = {t.id for t in local_results}
    final_results: List[dict] = []
    for t in local_results:
        row = t.model_dump()
        row["is_cached"] = t.is_cached
        final_results.append(row)

    if needed_from_yt <= 0 or not yt_data:
        return final_results

    yt_window = needed_from_yt * 3  # over-fetch factor for deduplication skips
    scan_pos = yt_offset

    while len(final_results) < limit and scan_pos < len(yt_data):
        window = yt_data[scan_pos : scan_pos + yt_window]
        scan_pos += len(window)

        window_remote_ids = [
            item["remote_id"] for item in window if item.get("remote_id")
        ]
        db_matches = _tracks_by_remote_id(session, window_remote_ids)

        for yt_item in window:
            if len(final_results) >= limit:
                break
            remote_id = yt_item.get("remote_id")
            if remote_id in db_matches:
                db_track = db_matches[remote_id]
                if db_track.id not in local_ids_in_results:
                    d = db_track.model_dump()
                    d["is_cached"] = db_track.is_cached
                    final_results.append(d)
                    local_ids_in_results.add(db_track.id)
            else:
                final_results.append(yt_item)

    return final_results


def _apply_is_liked_flags(session: Session, user: User, items: List[dict]) -> None:
    likes_stmt = select(UserActivity.track_id).where(
        UserActivity.user_id == user.id,
        UserActivity.is_liked,
    )
    likes = set(session.exec(likes_stmt).all())
    for item in items:
        item["is_liked"] = item.get("id") in likes


async def _resolved_stream_for_track(
    *,
    track_id: str,
    track: Optional[Track],
    library_uid: str,
    background_tasks: BackgroundTasks,
    session: Session,
) -> Any:
    """Return a FileResponse or live YouTube stream after auth checks."""
    min_youtube_cache_bytes = 100 * 1024
    min_local_bytes = 256

    if not track:
        if _looks_like_youtube_video_id(track_id):
            _logger.info("Streaming from YouTube (no DB row): %s", track_id)
            return await streamer.stream_youtube(
                track_id,
                allow_disk_cache=True,
                library_user_id=library_uid,
            )
        raise HTTPException(status_code=404, detail="Track not found")

    if track.source_type == "local":
        if track.local_path and os.path.exists(track.local_path):
            sz = os.path.getsize(track.local_path)
            if sz >= min_local_bytes:
                _logger.info(
                    "Streaming local library file: %s (%s bytes)", track.local_path, sz
                )
                return streamer.get_local_stream(track.local_path)
        raise HTTPException(
            status_code=404,
            detail="Local audio file not found on server",
        )

    if track.is_cached and track.local_path and os.path.exists(track.local_path):
        file_size = os.path.getsize(track.local_path)
        if file_size > min_youtube_cache_bytes:
            _logger.info(
                "Streaming from local cache: %s (%s bytes)", track.local_path, file_size
            )
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
        _logger.warning(
            "Cache file %s is suspiciously small (%d bytes). Invaliding.",
            track.local_path,
            file_size,
        )
        track.is_cached = False
        track.local_path = None
        session.add(track)
        session.commit()
    elif track.is_cached and track.local_path:
        _logger.warning(
            "Track marked as cached but file missing at: %s. Falling back to YT.",
            track.local_path,
        )
        track.is_cached = False
        track.local_path = None
        session.add(track)
        session.commit()

    if track.source_type != "youtube":
        raise HTTPException(
            status_code=503,
            detail=f"Streaming for source_type={track.source_type!r} is not supported",
        )
    if not track.remote_id or not _youtube_video_id_len_ok(track.remote_id):
        raise HTTPException(
            status_code=503,
            detail=(
                "YouTube track is missing a valid video id (remote_id); "
                "re-add or re-index the track"
            ),
        )

    remote_key = track.remote_id
    _logger.info("Streaming from YouTube: %s", remote_key)
    # Always allow validated on-disk cache (min-size check in streamer). When is_cached is
    # false but a healthy temp file exists (e.g. DB not updated yet), this still plays.
    return await streamer.stream_youtube(
        remote_key,
        allow_disk_cache=True,
        library_user_id=library_uid,
    )


async def _search_tracks_core(
    session: Session, q: str, offset: int, limit: int, start_time: float
) -> List[dict]:
    """Load local + YouTube rows for one search page (no liked flags)."""
    q_lower = q.lower()
    all_local_db = session.exec(select(Track)).all()
    all_local = _filter_local_tracks_for_query(all_local_db, q_lower)

    local_count = len(all_local)
    _logger.info(
        "Local search complete in %.3fs: %s matches.",
        time.time() - start_time,
        local_count,
    )

    local_results = all_local[offset : offset + limit] if offset < local_count else []

    needed_from_yt = limit - len(local_results)
    yt_offset = max(0, offset - local_count)

    yt_data: list = []
    if needed_from_yt > 0:
        yt_data = await _get_cached_or_fetch_youtube(q)

    merge_params = _YoutubeMergeParams(
        needed_from_yt=needed_from_yt,
        yt_offset=yt_offset,
        limit=limit,
        local_results=local_results,
    )
    return _merge_youtube_with_dedup(session, yt_data, merge_params)


@router.get("/search", response_model=List[dict])
@limiter.limit("90/minute")
async def search(
    request: Request,
    q: str,
    offset: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user),
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

    final_results = await _search_tracks_core(session, q, offset, limit, start_time)

    if current_user:
        _apply_is_liked_flags(session, current_user, final_results)

    _logger.info(
        "Search returned %s total results in %.3fs for: %s",
        len(final_results),
        time.time() - start_time,
        q,
    )
    return final_results


@router.get("/popular")
async def get_popular_tracks(
    offset: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user),
) -> List[dict]:
    """
    Fetch popular tracks from the local library based on global play counts.
    """
    # Query tracks and sum their play counts across all users
    statement = (
        select(Track, func.sum(UserActivity.play_count).label("total_plays"))
        .outerjoin(UserActivity, col(UserActivity.track_id) == col(Track.id))
        .group_by(Track.id)
        .order_by(
            desc(func.sum(UserActivity.play_count)),
            desc(col(Track.added_at)),
        )
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
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Toggle 'liked' status for a specific track.
    """
    _logger.info("User %s liking track %s: %s", current_user.id, track_id, is_liked)
    track = await ensure_track_exists(session, track_id)

    if not track:
        raise HTTPException(
            status_code=404, detail="Track not found and could not be indexed."
        )

    # Update user activity
    activity_statement = select(UserActivity).where(
        UserActivity.user_id == current_user.id, UserActivity.track_id == track.id
    )
    activity = session.exec(activity_statement).first()

    if not activity:
        activity = UserActivity(
            user_id=current_user.id, track_id=track.id, is_liked=is_liked
        )
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
    current_user: Optional[User] = Depends(get_optional_user),
) -> List[dict]:
    """
    Fetch recently added or modified tracks.
    """
    statement = (
        select(Track).order_by(col(Track.added_at).desc()).offset(offset).limit(limit)
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
    current_user: Optional[User] = Depends(get_optional_user),
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
        UserActivity.user_id == current_user.id, UserActivity.track_id == track.id
    )
    activity = session.exec(activity_statement).first()

    if not activity:
        activity = UserActivity(
            user_id=current_user.id,
            track_id=track.id,
            play_count=1,
            last_played=datetime.now(timezone.utc),
        )
        session.add(activity)
    else:
        activity.play_count += 1
        activity.last_played = datetime.now(timezone.utc)
        session.add(activity)

        # Trigger persistent caching on the 3rd play (YouTube sources only)
        if activity.play_count == 3 and track.remote_id:
            _logger.info(
                "Track %s reached threshold (3 plays). Promoting to persistent cache.",
                track.id,
            )
            promote_track_to_cache(track.remote_id)

    session.commit()
    return {"status": "success", "play_count": activity.play_count}


@router.get("/liked")
async def get_liked_tracks(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> List[dict]:
    """
    Fetch all tracks that the current user has 'liked', with thumbnail backfill.
    """
    statement = (
        select(Track)
        .join(UserActivity)
        .where(
            UserActivity.user_id == current_user.id,
            UserActivity.is_liked,
        )
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
    if not session.exec(statement).first() and not _looks_like_youtube_video_id(tid):
        raise HTTPException(status_code=404, detail="Track not found")
    exp = int(time.time()) + settings.STREAM_URL_TTL_SECONDS
    sig = sign_stream_url(tid, exp, current_user.id)
    base = api_v1_base_url(request)
    uid_q = quote(current_user.id, safe="")
    stream_url = f"{base}/tracks/stream/{tid}?exp={exp}&sig={sig}&uid={uid_q}"
    return {
        "stream_url": stream_url,
        "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(),
    }


@router.get("/stream/{track_id}")
@limiter.limit("200/minute")
async def stream_track(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
            detail=(
                "Valid stream credentials required; obtain a signed URL via "
                "POST .../tracks/stream/grant"
            ),
        )
    if not _valid_stream_track_id(track_id):
        raise HTTPException(status_code=400, detail="Invalid track_id")
    if not verify_stream_params(track_id, exp, uid, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired stream link")
    if not session.get(User, uid):
        raise HTTPException(status_code=403, detail="Invalid stream subject")
    library_uid = uid
    _logger.info("Streaming request for: %s", track_id)
    statement = select(Track).where(
        or_(Track.id == track_id, Track.remote_id == track_id)
    )
    track = session.exec(statement).first()
    return await _resolved_stream_for_track(
        track_id=track_id,
        track=track,
        library_uid=library_uid,
        background_tasks=background_tasks,
        session=session,
    )


@router.get("/{track_id}")
# Intentionally no rate limit (metadata fetches are lightweight; search is limited).
async def get_track(track_id: str, session: Session = Depends(get_session)) -> dict:
    """
    Fetch metadata for a single track by ID (internal or remote).
    """
    statement = select(Track).where(
        or_(Track.id == track_id, Track.remote_id == track_id)
    )
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
    statement = select(Track).where(
        or_(Track.id == track_id, Track.remote_id == track_id)
    )
    track = session.exec(statement).first()
    remote_key: str = track.remote_id if track and track.remote_id else track_id

    related = await get_related_tracks(remote_key)
    return related
