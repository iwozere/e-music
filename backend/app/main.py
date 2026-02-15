import os
import asyncio
import httpx
import threading
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Any

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select, or_, delete
from app.models import User, Track, UserActivity, Playlist, PlaylistTrack
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from fastapi import Form
from jose import jwt as jose_jwt

from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.auth_utils import create_access_token, get_password_hash, verify_password, verify_token
from app.db import init_db, get_session, engine
from app.models import User, Track, UserActivity
from app.indexer import run_indexer
from app.watcher import start_watcher
from app.services import ytmusic, streamer
from app.utils.logger import setup_logger
from google.oauth2 import id_token
from google.auth.transport import requests

_logger = setup_logger(__name__)

app = FastAPI(
    title="MySpotify API",
    description="Backend API for MySpotify music ecosystem."
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

# Search Cache: query -> {"results": List[dict], "expires": timestamp}
SEARCH_CACHE = {}
CACHE_TTL = 300 # 5 minutes

@app.on_event("startup")
def on_startup() -> None:
    """
    Bootstrap the application: init DB, start indexer and watcher.
    """
    _logger.info("Initializing MySpotify Backend...")
    init_db()
    # Run indexer on startup in background
    threading.Thread(target=run_indexer, daemon=True).start()
    # Start watcher in background
    threading.Thread(target=start_watcher, args=(settings.MUSIC_PATH,), daemon=True).start()
    _logger.info("Startup complete")

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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    session: Session = Depends(get_session)
) -> User:
    """
    Dependency to retrieve the current authenticated user from a JWT token.

    Args:
        token: Bearer token from the request header.
        session: Database session.

    Returns:
        The authenticated User instance.

    Raises:
        HTTPException: If the token is invalid or the user does not exist.
    """
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme), 
    session: Session = Depends(get_session)
) -> Optional[User]:
    """
    Optional dependency to retrieve the current user if a valid token is provided.
    """
    if not token or token in ["undefined", "null", "none"] or "." not in token:
        return None
    try:
        payload = verify_token(token)
        if payload is None:
            return None
        user_id = payload.get("sub")
        return session.get(User, user_id)
    except Exception:
        return None

async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency to ensure the current authenticated user has admin privileges.

    Args:
        current_user: The user instance from `get_current_user`.

    Returns:
        The User instance if they are an admin.

    Raises:
        HTTPException: If the user is not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

@app.get("/health")
async def health() -> dict:
    """
    Simple health check endpoint.
    """
    return {"status": "healthy"}

# Auth Endpoints
@app.post("/auth/register", response_model=User)
async def register(
    username: str, 
    email: str, 
    password: str, 
    session: Session = Depends(get_session)
) -> User:
    """
    Register a new user with username and password.
    """
    # Check if user exists
    _logger.info("Registering new user: %s", username)
    statement = select(User).where(or_(User.username == username, User.email == email))
    existing = session.exec(statement).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        hashed_password=get_password_hash(password),
        role="admin" if session.exec(select(User)).first() is None else "user"
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@app.post("/auth/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    session: Session = Depends(get_session)
) -> dict:
    """
    OAuth2 compatible token login, retrieve an access token for future requests.
    """
    _logger.info("Token login attempt for: %s", form_data.username)
    statement = select(User).where(User.username == form_data.username)
    user = session.exec(statement).first()
    if not user or not user.hashed_password or not verify_password(form_data.password, user.hashed_password):
        _logger.warning("Failed login attempt for: %s", form_data.username)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token = create_access_token(
        data={"sub": user.id, "email": user.email, "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/auth/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)) -> User:
    """
    Get current user's profile information.
    """
    return current_user

@app.get("/auth/login")
async def login() -> dict:
    """
    Get the Google OAuth2 authorization URL.
    """
    google_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={settings.GOOGLE_CLIENT_ID}&"
        f"redirect_uri={settings.GOOGLE_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=openid%20email%20profile"
    )
    return {"url": google_url}

@app.get("/auth/callback")
async def auth_callback(code: str, session: Session = Depends(get_session)) -> dict:
    """
    Handle the Google OAuth2 callback.
    """
    _logger.info("Handling Google OAuth2 callback")
    # Exchange code for token
    async with httpx.AsyncClient() as client:
        payload = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        
        token_response = await client.post("https://oauth2.googleapis.com/token", data=payload)
        token_data = token_response.json()
        
        # fallback for mobile/Android codes which might not expect a redirect_uri 
        # or have a different one configured in the Google Console.
        if "error" in token_data:
            _logger.info("Retrying Google token exchange without redirect_uri...")
            payload.pop("redirect_uri", None)
            token_response = await client.post("https://oauth2.googleapis.com/token", data=payload)
            token_data = token_response.json()

        if "error" in token_data:
            _logger.error("Google Auth error: %s", token_data.get("error_description"))
            raise HTTPException(status_code=400, detail=token_data.get("error_description"))
        
        id_token = token_data.get("id_token")
        decoded_id = jose_jwt.get_unverified_claims(id_token)
        
        email = decoded_id.get("email")
        google_id = decoded_id.get("sub")
        
        # Check if user exists
        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()
        
        if not user:
            _logger.info("Creating new Google user: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role="admin" if session.exec(select(User)).first() is None else "user"
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            
        access_token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role
            }
        }

@app.post("/auth/google")
async def google_auth(token_data: dict, session: Session = Depends(get_session)) -> dict:
    """
    Handle Google Auth via ID Token (Web GSI or Mobile).
    """
    token = token_data.get("id_token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing id_token")
    
    try:
        # Verify the ID token
        idinfo = id_token.verify_oauth2_token(token, requests.Request(), settings.GOOGLE_CLIENT_ID)
        
        email = idinfo["email"]
        google_id = idinfo["sub"]
        
        # Check if user exists
        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()
        
        if not user:
            _logger.info("Creating new Google user: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role="admin" if session.exec(select(User)).first() is None else "user"
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            
        access_token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role
            }
        }
    except ValueError as e:
        _logger.error("Invalid Google Token: %s", str(e))
        raise HTTPException(status_code=401, detail="Invalid Google token")

@app.post("/auth/google/login")
async def google_login_redirect(
    request: Request, 
    credential: str = Form(...), 
    session: Session = Depends(get_session)
) -> Any:
    """
    Handle Google GSI redirect mode POST.
    Verifies the credential and redirects the user back to the frontend with the token.
    """
    try:
        # Verify the ID token (credential)
        idinfo = id_token.verify_oauth2_token(credential, requests.Request(), settings.GOOGLE_CLIENT_ID)
        
        email = idinfo["email"]
        google_id = idinfo["sub"]
        
        # Check if user exists
        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()
        
        if not user:
            _logger.info("Creating new Google user from redirect: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role="admin" if session.exec(select(User)).first() is None else "user"
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            
        access_token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role}
        )
        
        # Redirect back to the frontend with the token in a hash fragment
        # Attempt to detect the return URL from the Referer header (provided by Google)
        referer = request.headers.get("referer")
        if referer and ("localhost" in referer or "127.0.0.1" in referer):
            # Extract base URL (e.g., http://localhost:8000)
            from urllib.parse import urlparse
            p = urlparse(referer)
            base_url = f"{p.scheme}://{p.netloc}"
        else:
            base_url = f"https://{settings.DOMAIN}"
            
        from fastapi.responses import RedirectResponse
        frontend_url = f"{base_url}/#token={access_token}"
        _logger.info("Redirecting back to: %s", base_url)
        return RedirectResponse(url=frontend_url, status_code=303)
        
    except ValueError as e:
        _logger.error("Invalid Google Token in redirect: %s", str(e))
        raise HTTPException(status_code=401, detail="Invalid Google token")

@app.get("/auth/config")
async def get_auth_config(request: Request) -> dict:
    """
    Expose public configuration for the frontend auth.
    """
    return {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
        "api_base_url": str(request.base_url).rstrip('/')
    }

@app.get("/system/config")
async def get_system_config() -> dict:
    # Keeping this for a brief transition / debugging
    return await get_auth_config()

@app.post("/system/index")
async def trigger_index(background_tasks: BackgroundTasks) -> dict:
    """
    Manually trigger a full library index scan.
    """
    _logger.info("Manual index triggered")
    background_tasks.add_task(run_indexer)
    return {"message": "Indexing started in background"}

# System Info
@app.get("/system/storage")
async def get_storage() -> dict:
    """
    Get backend server storage statistics.
    """
    import psutil
    path = "/app"
    usage = psutil.disk_usage(path)
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": usage.percent
    }

# Track Endpoints
@app.get("/search")
async def search(
    q: str, 
    offset: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session), 
    current_user: Optional[User] = Depends(get_current_user)
) -> List[dict]:
    """
    Search for tracks across local library and YouTube Music.
    Uses in-memory caching to optimize paginated requests.
    """
    _logger.info("Searching for: %s (offset: %s, limit: %s)", q, offset, limit)
    
    # 1. Check Cache
    now = datetime.now().timestamp()
    if q in SEARCH_CACHE and SEARCH_CACHE[q]["expires"] > now:
        _logger.info("Serving YouTube results from cache for: %s", q)
        yt_results = SEARCH_CACHE[q]["results"]
    else:
        # Fetch a large batch to pre-populate future pages
        yt_limit = 100 
        try:
            yt_results = await asyncio.to_thread(ytmusic.search_youtube, q, limit=yt_limit)
            SEARCH_CACHE[q] = {
                "results": yt_results,
                "expires": now + CACHE_TTL
            }
        except Exception:
            _logger.exception("YouTube Search Error")
            yt_results = []
    
    # 2. Search local DB (fast) with pagination
    # Note: We still do local DB search every time to ensure we get new local additions
    statement = select(Track).where(
        or_(
            Track.title.contains(q),
            Track.artist.contains(q),
            Track.album.contains(q)
        )
    ).offset(offset).limit(limit)
    local_results = session.exec(statement).all()
        
    final_results = []
    cached_tracks = {t.remote_id: t for t in local_results if t.remote_id}
    
    # Add local results first
    final_results.extend([t.dict() for t in local_results])
    
    # Slice YT results to match the current "page"
    current_yt_page = yt_results[offset:offset+limit] if len(yt_results) > offset else []

    # Add YT results if not already present in local results
    for yt_item in current_yt_page:
        remote_id = yt_item["remote_id"]
        if remote_id not in cached_tracks:
            db_track = session.exec(select(Track).where(Track.remote_id == remote_id)).first()
            if db_track:
                # Lazy backfill: Update thumbnail if missing
                if yt_item.get("thumbnail") and not db_track.thumbnail:
                    db_track.thumbnail = yt_item["thumbnail"]
                    session.add(db_track)
                    session.commit()
                    session.refresh(db_track)
                final_results.append(db_track.dict())
                cached_tracks[remote_id] = db_track
            else:
                final_results.append(yt_item)
                cached_tracks[remote_id] = yt_item
            
    # Enrich with liked status
    if current_user:
        likes_statement = select(UserActivity).where(
            UserActivity.user_id == current_user.id, 
            UserActivity.is_liked == True
        )
        likes = {a.track_id for a in session.exec(likes_statement).all()}
        for item in final_results:
            item["is_liked"] = (item.get("id") in likes) or \
                (session.exec(select(Track.id).where(Track.remote_id == item.get("remote_id"))).first() in likes)

    return final_results

@app.get("/tracks/popular")
async def get_popular_tracks(
    offset: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user)
) -> List[dict]:
    """
    Fetch popular tracks from the local library based on global play counts.
    """
    from sqlalchemy import func
    
    # Query tracks and sum their play counts across all users
    statement = (
        select(Track, func.sum(UserActivity.play_count).label("total_plays"))
        .join(UserActivity, UserActivity.track_id == Track.id, isouter=True)
        .group_by(Track.id)
        .order_by(func.sum(UserActivity.play_count).desc(), Track.added_at.desc())
        .offset(offset)
        .limit(limit)
    )
    results = session.exec(statement).all()
    
    final_results = []
    
    # Get user likes if logged in
    likes = set()
    if current_user:
        likes_stmt = select(UserActivity.track_id).where(UserActivity.user_id == current_user.id, UserActivity.is_liked == True)
        likes = set(session.exec(likes_stmt).all())

    for track, total_plays in results:
        t_dict = track.dict()
        t_dict["is_liked"] = t_dict["id"] in likes
        t_dict["total_plays"] = int(total_plays or 0)
        final_results.append(t_dict)
        
    return final_results

@app.post("/tracks/{track_id}/like")
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

@app.post("/tracks/{track_id}/play")
async def track_played(
    track_id: str, 
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Record a play event for a track and increment play count.
    """
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
        
        # Trigger persistent caching on the 3rd play
        if activity.play_count == 3:
            _logger.info("Track %s reached threshold (3 plays). Promoting to persistent cache.", track.id)
            from app.services.cache_manager import promote_track_to_cache
            # Since streamer.py currently caches everything, we might just need to ensure 
            # it's marked as 'protected' or moved to a specific folder.
            # For now, we'll let streamer.py handle the heavy lifting and CacheManager handle cleanup.
            promote_track_to_cache(track.remote_id)
    
    session.commit()
    return {"status": "success", "play_count": activity.play_count}

@app.get("/tracks/liked")
async def get_liked_tracks(
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> List[dict]:
    """
    Fetch all tracks that the current user has 'liked', with thumbnail backfill.
    """
    statement = select(Track).join(UserActivity).where(
        UserActivity.user_id == current_user.id,
        UserActivity.is_liked == True
    )
    liked_tracks = session.exec(statement).all()
    
    results = []
    updated = False
    for t in liked_tracks:
        track_dict = t.dict()
        # Proactive Backfill: If YT track missing thumbnail, fetch it now
        if t.source_type == "youtube" and not t.thumbnail and t.remote_id:
            try:
                _logger.info("Proactively fetching thumbnail for liked track: %s", t.title)
                yt_info = await asyncio.to_thread(ytmusic.yt.get_song, t.remote_id)
                if yt_info and "videoDetails" in yt_info:
                    details = yt_info["videoDetails"]
                    thumbnails = details.get("thumbnail", {}).get("thumbnails", [])
                    if thumbnails:
                        t.thumbnail = thumbnails[-1].get("url")
                        track_dict["thumbnail"] = t.thumbnail
                        session.add(t)
                        updated = True
            except Exception:
                _logger.warning("Failed to proactive backfill thumbnail for %s", t.remote_id)
        
        results.append(track_dict)
    
    if updated:
        session.commit()
        
    return results

@app.get("/tracks/{track_id}")
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
    
    # Optional backfill here too
    if track.source_type == "youtube" and not track.thumbnail and track.remote_id:
        try:
            yt_info = await asyncio.to_thread(ytmusic.yt.get_song, track.remote_id)
            if yt_info and "videoDetails" in yt_info:
                details = yt_info["videoDetails"]
                thumbnails = details.get("thumbnail", {}).get("thumbnails", [])
                if thumbnails:
                    track.thumbnail = thumbnails[-1].get("url")
                    session.add(track)
                    session.commit()
                    session.refresh(track)
        except Exception: pass

    return track.dict()

@app.get("/tracks/{track_id}/related")
async def get_related(
    track_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> List[dict]:
    """
    Radio Mode: Fetch related tracks based on a track ID.
    """
    _logger.info("Radio Mode requested for track: %s", track_id)
    # 1. Identify the track to get the remote_id
    statement = select(Track).where(or_(Track.id == track_id, Track.remote_id == track_id))
    track = session.exec(statement).first()
    
    remote_id = track.remote_id if track else track_id
    
    # 2. Fetch related from YT
    from app.services.ytmusic import get_related_tracks
    related = get_related_tracks(remote_id)
    
    return related

# Playlist Endpoints
@app.get("/playlists")
async def get_playlists(
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> List[dict]:
    """
    Fetch all playlists owned by the current user.
    """
    statement = select(Playlist).where(Playlist.owner_id == current_user.id)
    playlists = session.exec(statement).all()
    return [p.dict() for p in playlists]

@app.post("/playlists")
async def create_playlist(
    name: str = Form(...), 
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Create a new playlist for the current user.
    """
    import uuid
    new_playlist = Playlist(
        id=str(uuid.uuid4()),
        name=name,
        owner_id=current_user.id
    )
    session.add(new_playlist)
    session.commit()
    session.refresh(new_playlist)
    return new_playlist.dict()

@app.post("/playlists/{playlist_id}/tracks")
async def add_track_to_playlist(
    playlist_id: str,
    track_id: str = Form(...),
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Add a track to a specific playlist.
    """
    # 1. Verify playlist ownership
    playlist = session.exec(select(Playlist).where(
        Playlist.id == playlist_id, 
        Playlist.owner_id == current_user.id
    )).first()
    
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # 2. Ensure track exists and get real DB ID
    track = await ensure_track_exists(session, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track could not be found or indexed.")

    # 3. Get current max position
    count_stmt = select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
    existing_tracks = session.exec(count_stmt).all()
    next_pos = len(existing_tracks)

    # 4. Add relation using the database Track.id
    new_rel = PlaylistTrack(playlist_id=playlist_id, track_id=track.id, position=next_pos)
    session.add(new_rel)
    session.commit()
    return {"status": "success"}

@app.get("/playlists/{playlist_id}/tracks")
async def get_playlist_tracks(
    playlist_id: str,
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> List[dict]:
    """
    Fetch all tracks in a specific playlist, ordered by position.
    """
    # 1. Verify ownership
    playlist = session.exec(select(Playlist).where(
        Playlist.id == playlist_id, 
        Playlist.owner_id == current_user.id
    )).first()
    
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # 2. Get tracks with enrichment
    statement = (
        select(Track, PlaylistTrack.position)
        .join(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    )
    result = session.exec(statement).all()
    
    # 3. Format response with backfill
    tracks_list = []
    updated = False
    for track, position in result:
        t_dict = track.dict()
        t_dict["playlist_position"] = position
        
        # Lazy backfill for playlists
        if track.source_type == "youtube" and not track.thumbnail and track.remote_id:
            try:
                _logger.info("Backfilling playlist track: %s", track.title)
                yt_info = await asyncio.to_thread(ytmusic.yt.get_song, track.remote_id)
                if yt_info and "videoDetails" in yt_info:
                    details = yt_info["videoDetails"]
                    thumbnails = details.get("thumbnail", {}).get("thumbnails", [])
                    if thumbnails:
                        track.thumbnail = thumbnails[-1].get("url")
                        t_dict["thumbnail"] = track.thumbnail
                        session.add(track)
                        updated = True
            except Exception: pass
            
        tracks_list.append(t_dict)
    
    if updated:
        session.commit()
        
    return tracks_list

@app.delete("/playlists/{playlist_id}")
async def delete_playlist(
    playlist_id: str,
    session: Session = Depends(get_session), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Delete a user's playlist.
    """
    playlist = session.exec(select(Playlist).where(
        Playlist.id == playlist_id, 
        Playlist.owner_id == current_user.id
    )).first()
    
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    session.delete(playlist)
    # Also delete associations
    session.exec(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
    session.commit()
    return {"status": "success"}

@app.get("/stream/{track_id}")
async def stream_track(track_id: str, session: Session = Depends(get_session)) -> Any:
    """
    Stream a track's audio data. Handles local files, cached YT tracks, and live YT streaming.
    """
    _logger.info("Streaming request for: %s", track_id)
    statement = select(Track).where(or_(Track.id == track_id, Track.remote_id == track_id))
    track = session.exec(statement).first()
    
    if track and track.is_cached and track.local_path:
        _logger.info("Streaming from local cache: %s", track.local_path)
        return streamer.get_local_stream(track.local_path)
    
    _logger.info("Streaming from YouTube: %s", track.remote_id if track else track_id)
    return await streamer.stream_youtube(track.remote_id if track else track_id)

# Mount the web frontend (Static HTML/JS/CSS)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # Catch-all for SPA: serve index.html for the root
    @app.get("/")
    async def read_index():
        from fastapi.responses import FileResponse
        return FileResponse(os.path.join(static_dir, "index.html"))
else:
    _logger.warning("Web static folder '%s' not found. Frontend will not be served.", static_dir)
